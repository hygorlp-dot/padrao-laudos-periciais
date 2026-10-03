import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.terceiros import verificar_professional_ux, verificar_superpowers
from scripts.terceiros.verificar_superpowers import verificar


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_TREES = {
    "test-driven-development", "systematic-debugging",
    "verification-before-completion", "requesting-code-review",
    "receiving-code-review", "writing-plans", "executing-plans",
    "using-superpowers",
}
# Decisão humana na #276 (opção A): árvores novas pinadas no commit 8ca22db.
PROFESSIONAL_UX_TREES = {
    "brainstorming", "using-git-worktrees", "subagent-driven-development",
    "dispatching-parallel-agents", "finishing-a-development-branch",
}
PROFESSIONAL_UX_COMMIT = "8ca22dba9a94f28898bbce59f2537ff4d87c747d"
BRAINSTORMING_ALLOWLIST = {"SKILL.md", "spec-document-reviewer-prompt.md"}
EXCLUDED_CAPABILITY_MARKERS = (
    "server.cjs", "start-server", "stop-server", "createServer", "visual-companion.md",
    "primeradiant.com", "superpowers-visual-brainstorming-logo",
)
# Toda Skill instalada tem de estar coberta por um manifesto de integridade ou
# ser first-party/catalogada; uma Skill nova sem classificação falha fechado.
FIRST_PARTY_SKILLS = {
    "auditoria-grounding-pericial", "auditoria-linguagem-pericial", "auditoria-pericial-continua",
    "auditoria-pericial-integrada", "autonomia-desenvolvimento", "engenharia-seguranca-pericial",
    "external-diversity-review", "motor-vicios-construtivos", "planejamento-pericial-autonomo",
    "redacao-laudo-pericial", "repository-safety-gate", "research-ranking", "reviewer-independente",
    "revisao-laudo-pericial", "systemic-auditor", "triagem-delimitacao-pericial",
    "trilha-auditoria-pericial", "ui-pericial",
}
LICENSE_CATALOGUED_THIRD_PARTY = {"impeccable", "claim-audit", "proposition-audit"}
SINGLE_MANIFEST_THIRD_PARTY = {"frontend-design", "design-motion-principles"}


def _isolated_root(target):
    """Cópia mínima do repositório para provar falhas sem tocar a árvore real."""
    for relative in (".agents", "docs/terceiros", "AGENTS.md"):
        source = ROOT / relative
        destination = target / relative
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    return target


def _superpowers_errors(root):
    with mock.patch.object(verificar_superpowers, "ROOT", root), \
            mock.patch.object(verificar_superpowers, "MANIFEST", root / "docs/terceiros/superpowers-manifest.json"), \
            mock.patch.object(verificar_superpowers, "LICENSE", root / ".agents/third-party/superpowers/LICENSE"):
        return verificar_superpowers.verificar()


def _tree_source_problems(manifest):
    problems = []
    sources = manifest.get("tree_sources", {})
    for name in sorted(PROFESSIONAL_UX_TREES):
        source = sources.get(name)
        if source is None:
            problems.append(f"TREE_SOURCE_MISSING {name}")
            continue
        if source.get("commit") != PROFESSIONAL_UX_COMMIT:
            problems.append(f"TREE_SOURCE_COMMIT {name}")
        if source.get("upstream_tree") != manifest["skill_trees"].get(name):
            problems.append(f"TREE_SOURCE_TREE {name}")
    for name in sorted(set(sources) - PROFESSIONAL_UX_TREES):
        problems.append(f"TREE_SOURCE_UNEXPECTED {name}")
    return problems


def _routing_problems(router, installed):
    routed = set(router.get("reference_only", [])) | set(router.get("material_bundle", []))
    for profile in router.get("profiles", {}).values():
        routed.update(profile.get("required", []))
        for skills in profile.get("conditional", {}).values():
            routed.update(skills)
    return sorted(f"ROUTED_NOT_INSTALLED {name}" for name in routed - installed) + sorted(
        f"INSTALLED_NOT_ROUTED {name}" for name in installed - routed
    )


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
        self.assertEqual(set(manifest["skill_trees"]), ORIGINAL_TREES | PROFESSIONAL_UX_TREES)
        self.assertEqual(_tree_source_problems(manifest), [])
        for name, source in manifest["tree_sources"].items():
            self.assertEqual(source["repository"], "https://github.com/obra/superpowers")
            self.assertEqual(source["local_path"], f".agents/skills/{name}")

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
        self.assertEqual(set(manifest["skill_trees"]), selected | PROFESSIONAL_UX_TREES)

    def test_brainstorming_is_textual_and_local_only(self):
        # Opção A (#276): BRAINSTORMING_POLICY = TEXTUAL_AND_LOCAL_ONLY.
        folder = ROOT / ".agents/skills/brainstorming"
        self.assertTrue((folder / "SKILL.md").is_file())
        files = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
        self.assertEqual(files, BRAINSTORMING_ALLOWLIST)
        self.assertFalse((folder / "scripts").exists())
        self.assertFalse((folder / "visual-companion.md").exists())
        for path in folder.rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for marker in EXCLUDED_CAPABILITY_MARKERS:
                    self.assertNotIn(marker, text, f"{path.name}: {marker}")
                self.assertNotRegex(text, r"https?://")
        policy = json.loads((ROOT / ".agents/superpowers-policy.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["brainstorming_policy"], "TEXTUAL_AND_LOCAL_ONLY")
        self.assertIn("brainstorming-server", policy["excluded_network_capabilities"])
        self.assertIn("remote-brand-image", policy["excluded_network_capabilities"])
        source = json.loads((ROOT / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))["tree_sources"]["brainstorming"]
        self.assertEqual(source["integration"], "RESTRICTED")
        self.assertEqual(set(source["local_allowlist"]), BRAINSTORMING_ALLOWLIST)
        self.assertEqual(set(source["excluded_capabilities"]), {"brainstorming-server", "remote-brand-image"})
        for excluded in source["excluded_paths"]:
            self.assertFalse((folder / excluded).exists(), excluded)

    def test_every_installed_skill_is_classified_and_integrity_covered(self):
        installed = {path.name for path in (ROOT / ".agents/skills").iterdir() if path.is_dir()}
        superpowers = set(json.loads((ROOT / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))["skill_trees"])
        professional = {entry["name"] for entry in json.loads((ROOT / "docs/terceiros/professional-ux-v1-blobs.json").read_text(encoding="utf-8"))["skills"]}
        classified = FIRST_PARTY_SKILLS | LICENSE_CATALOGUED_THIRD_PARTY | SINGLE_MANIFEST_THIRD_PARTY | superpowers | professional
        self.assertEqual(installed - classified, set(), "Skill vendorizada sem classificação/manifesto")
        self.assertEqual(superpowers & professional, set())
        router = json.loads((ROOT / ".agents/skill-router.json").read_text(encoding="utf-8"))
        self.assertEqual(_routing_problems(router, installed), [])

    def test_professional_ux_third_party_skills_are_pinned(self):
        self.assertEqual(verificar_professional_ux.verificar(), [])

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


class SuperpowersAdversarialTest(unittest.TestCase):
    """Cada violação determinística da opção A tem de falhar fechado."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _isolated_root(Path(self._tmp.name))
        self.assertEqual(_superpowers_errors(self.root), [])
        self.assertEqual(verificar_professional_ux.verificar(self.root), [])

    def tearDown(self):
        self._tmp.cleanup()

    def test_reintroduced_server_fails(self):
        target = self.root / ".agents/skills/brainstorming/scripts/server.cjs"
        target.parent.mkdir()
        target.write_text("require('http').createServer().listen(0)\n", encoding="utf-8")
        self.assertTrue(any(item.startswith("FILE_SET") for item in _superpowers_errors(self.root)))

    def test_reintroduced_visual_companion_fails(self):
        (self.root / ".agents/skills/brainstorming/visual-companion.md").write_text("# companion\n", encoding="utf-8")
        self.assertTrue(any(item.startswith("FILE_SET") for item in _superpowers_errors(self.root)))

    def test_remote_brand_image_reference_fails(self):
        skill = self.root / ".agents/skills/brainstorming/SKILL.md"
        skill.write_text(skill.read_text(encoding="utf-8") + "\n![](https://primeradiant.com/brand/logo.png)\n", encoding="utf-8")
        self.assertIn("BLOB .agents/skills/brainstorming/SKILL.md", _superpowers_errors(self.root))

    def test_altered_blob_fails(self):
        for relative in (".agents/skills/using-git-worktrees/SKILL.md", ".agents/skills/playwright-cli/references/tracing.md"):
            path = self.root / relative
            path.write_bytes(path.read_bytes() + b"\n")
        self.assertIn("BLOB .agents/skills/using-git-worktrees/SKILL.md", _superpowers_errors(self.root))
        self.assertIn("BLOB playwright-cli/references/tracing.md", verificar_professional_ux.verificar(self.root))

    def test_new_vendored_file_or_skill_without_manifest_fails(self):
        extra = self.root / ".agents/skills/vercel-react-best-practices/rules/extra.md"
        extra.parent.mkdir()
        extra.write_text("unpinned\n", encoding="utf-8")
        self.assertTrue(any(item.startswith("FILE_SET vercel-react-best-practices") for item in verificar_professional_ux.verificar(self.root)))
        (self.root / ".agents/skills/unpinned-skill").mkdir()
        (self.root / ".agents/skills/unpinned-skill/SKILL.md").write_text("x\n", encoding="utf-8")
        installed = {path.name for path in (self.root / ".agents/skills").iterdir() if path.is_dir()}
        superpowers = set(json.loads((self.root / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))["skill_trees"])
        professional = {entry["name"] for entry in json.loads((self.root / "docs/terceiros/professional-ux-v1-blobs.json").read_text(encoding="utf-8"))["skills"]}
        classified = FIRST_PARTY_SKILLS | LICENSE_CATALOGUED_THIRD_PARTY | SINGLE_MANIFEST_THIRD_PARTY | superpowers | professional
        self.assertEqual(installed - classified, {"unpinned-skill"})

    def test_upstream_commit_divergence_fails(self):
        manifest_path = self.root / "docs/terceiros/professional-ux-v1-blobs.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["skills"][0]["commit"] = "0" * 40
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        errors = verificar_professional_ux.verificar(self.root)
        self.assertIn("MANIFEST divergente do contrato pinado", errors)
        self.assertIn("COMMIT vercel-react-best-practices", errors)
        manifest = json.loads((self.root / "docs/terceiros/superpowers-manifest.json").read_text(encoding="utf-8"))
        manifest["tree_sources"]["brainstorming"]["commit"] = "0" * 40
        del manifest["tree_sources"]["using-git-worktrees"]
        self.assertEqual(_tree_source_problems(manifest), [
            "TREE_SOURCE_COMMIT brainstorming", "TREE_SOURCE_MISSING using-git-worktrees",
        ])

    def test_router_ghost_skill_and_unrouted_skill_fail(self):
        router = json.loads((self.root / ".agents/skill-router.json").read_text(encoding="utf-8"))
        installed = {path.name for path in (self.root / ".agents/skills").iterdir() if path.is_dir()}
        router["profiles"]["ui"]["conditional"]["browser_qa"] = ["ghost-skill"]
        self.assertEqual(_routing_problems(router, installed), ["ROUTED_NOT_INSTALLED ghost-skill", "INSTALLED_NOT_ROUTED playwright-cli"])

    def test_network_skill_cannot_become_executable_route(self):
        router_path = self.root / ".agents/skill-router.json"
        router = json.loads(router_path.read_text(encoding="utf-8"))
        router["profiles"]["ui"]["conditional"]["product_discovery"].append("find-skills")
        router["reference_only"].remove("web-design-guidelines")
        router_path.write_text(json.dumps(router), encoding="utf-8")
        errors = verificar_professional_ux.verificar(self.root)
        self.assertIn("NETWORK_SKILL_ROUTED find-skills", errors)
        self.assertIn("NETWORK_SKILL_NOT_REFERENCE_ONLY web-design-guidelines", errors)
