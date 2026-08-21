import json
import re
import subprocess
import unittest
from pathlib import Path
from scripts.terceiros.catalogar_repositorios import _frontmatter,_licenca
RAIZ=Path(__file__).resolve().parents[1]
class IntegracoesExternasTest(unittest.TestCase):
    def _imports_relativos_ausentes(self,raiz):
        padrao=re.compile(r'''(?:from\s*|import\s*\(|require\s*\()\s*["'](\.[^"']+)["']''');ausentes=[]
        for arquivo in raiz.rglob("*"):
            if not arquivo.is_file() or arquivo.suffix not in {".js",".mjs",".cjs",".ts"}:continue
            for alvo in padrao.findall(arquivo.read_text(encoding="utf-8")):
                base=arquivo.parent/alvo;candidatos=[base,*[Path(str(base)+e) for e in (".js",".mjs",".cjs",".ts",".json")],*[base/f"index{e}" for e in (".js",".mjs",".cjs",".ts")]]
                if not any(x.is_file() for x in candidatos):ausentes.append((arquivo.relative_to(raiz).as_posix(),alvo))
        return ausentes
    def test_skills_seletivas_e_atribuicoes_presentes(self):
        for nome in ("impeccable","claim-audit","proposition-audit"):
            pasta=RAIZ/".agents/skills"/nome;self.assertTrue((pasta/"SKILL.md").exists());self.assertTrue((pasta/"LICENSE").exists())
    def test_nenhum_hook_codex_foi_inventado(self):self.assertFalse((RAIZ/".codex/hooks.json").exists())
    def test_skill_agpl_nao_foi_copiada(self):self.assertFalse((RAIZ/".agents/skills/ai-audit-trail").exists())
    def test_frontend_design_oficial_esta_pinado_e_integro(self):
        manifesto_path=RAIZ/"docs/terceiros/frontend-design-blobs.json"
        self.assertTrue(manifesto_path.is_file())
        manifesto=json.loads(manifesto_path.read_text(encoding="utf-8"))
        self.assertEqual(manifesto["repo"],"https://github.com/anthropics/claude-plugins-official")
        self.assertEqual(manifesto["commit"],"67a666efc8524ff7abaa266f84e514aa77aee48f")
        self.assertEqual(manifesto["upstream_path"],"plugins/frontend-design/skills/frontend-design")
        self.assertEqual(manifesto["license"],"Apache-2.0")
        self.assertEqual(manifesto["mode"],"THIRD_PARTY_SKILL_PINNED_BYTE_EXACT")
        self.assertEqual(manifesto["destination"],".agents/skills/frontend-design")
        self.assertEqual(set(manifesto["blobs"]),{"SKILL.md","LICENSE.txt"})
        pasta=RAIZ/manifesto["destination"]
        self.assertEqual({p.name for p in pasta.iterdir() if p.is_file()},{"SKILL.md","LICENSE.txt"})
        from scripts.terceiros.verificar_frontend_design import verificar
        self.assertEqual(verificar(),[])
    def test_catalogador_identifica_licencas(self):
        self.assertEqual(_licenca(RAIZ/".agents/skills/claim-audit/LICENSE"),"MIT");self.assertEqual(_licenca(RAIZ/".agents/skills/impeccable/LICENSE"),"Apache-2.0")
        self.assertIn("name",_frontmatter(RAIZ/".agents/skills/proposition-audit/SKILL.md"))
    def test_impeccable_limitado_a_frontend(self):
        descricao=_frontmatter(RAIZ/".agents/skills/impeccable/SKILL.md")["description"].lower();self.assertIn("frontend",descricao);self.assertIn("not for backend",descricao)
    def test_ferramenta_de_rede_exige_egresso_e_nao_integra_pipeline(self):
        politica=(RAIZ/"docs/terceiros/integracoes-agentes.md").read_text(encoding="utf-8")
        self.assertIn("EXTERNAL_DATA_EGRESS_REQUIRED",politica);self.assertIn("generate-image.mjs",politica)
        pipeline=(RAIZ/"scripts/motor_vicios/pipeline.py").read_text(encoding="utf-8")
        self.assertNotIn("generate-image",pipeline);self.assertNotIn("impeccable",pipeline)
        inventario=(RAIZ/"docs/terceiros/egresso-rede.md").read_text(encoding="utf-8");self.assertIn("EXTERNAL_DATA_EGRESS_REQUIRED",inventario);self.assertIn("concept-seed.mjs",inventario);self.assertIn("context.mjs",inventario)
    def test_impeccable_completo_e_imports_relativos_resolvidos(self):
        pasta=RAIZ/".agents/skills/impeccable";lib=pasta/"scripts/lib";self.assertEqual(len([p for p in pasta.rglob("*") if p.is_file()]),155);self.assertEqual(len(list(lib.glob("*.mjs"))),17);self.assertEqual(self._imports_relativos_ausentes(pasta),[])
    def test_impeccable_possui_atribuicoes_requeridas(self):
        pasta=RAIZ/".agents/skills/impeccable";self.assertTrue((pasta/"LICENSE").is_file());self.assertTrue((pasta/"NOTICE.md").is_file());self.assertTrue((pasta/"SKILL.md").is_file())
    def test_fontes_requeridas_nao_estao_ignoradas(self):
        if not (RAIZ/".git").exists():self.skipTest("árvore exportada sem metadados Git; auditoria de composição roda externamente")
        arquivos=[p.relative_to(RAIZ).as_posix() for p in (RAIZ/".agents/skills/impeccable").rglob("*") if p.is_file()];r=subprocess.run(["git","check-ignore","--stdin"],cwd=RAIZ,input="\n".join(arquivos),text=True,capture_output=True);self.assertEqual(r.stdout.strip(),"",f"REQUIRED_THIRD_PARTY_FILE_IGNORED: {r.stdout}")
    def test_catalogo_privado_nao_esta_versionado(self):
        if not (RAIZ/".git").exists():self.skipTest("árvore exportada sem metadados Git")
        r=subprocess.run(["git","ls-files","referencias/privadas/*"],cwd=RAIZ,text=True,capture_output=True,check=True);self.assertEqual(r.stdout.strip(),"")
if __name__=="__main__":unittest.main()
