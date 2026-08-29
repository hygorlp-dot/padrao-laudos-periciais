import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource

from scripts.quality.skill_routing import route

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / ".agents/skill-router.json").read_text(encoding="utf-8"))


def test_manifest_is_closed_valid_and_routes_every_installed_skill():
    schema = json.loads((ROOT / "schemas/skill-router-v3.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(MANIFEST, schema)
    installed = {path.name for path in (ROOT / ".agents/skills").iterdir() if path.is_dir()}
    routed = set(MANIFEST["reference_only"]) | set(MANIFEST["material_bundle"])
    for profile in MANIFEST["profiles"].values():
        routed.update(profile["required"])
        for skills in profile["conditional"].values(): routed.update(skills)
    assert routed == installed
    assert MANIFEST["precedence"][0] == "AGENTS.md"


def test_router_schema_composes_with_global_schema_registry():
    schemas = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (ROOT / "schemas").glob("*.schema.json")
    ]
    Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )


def test_material_bug_loads_minimum_engineering_set_only():
    result = route(MANIFEST, profiles=["engineering"], conditions={"reproduced_bug"}, material=True, repository_mutation=True)
    assert result["status"] == "PASS"
    assert result["ordered_skills"] == ["engenharia-seguranca-pericial", "test-driven-development", "verification-before-completion", "repository-safety-gate", "autonomia-desenvolvimento", "systematic-debugging"]
    assert "ui-pericial" not in result["ordered_skills"]


def test_ui_has_one_entrypoint_and_polish_is_not_default():
    ordinary = route(MANIFEST, profiles=["ui"], conditions=set(), material=True, repository_mutation=True)["ordered_skills"]
    assert ordinary[-3:] == ["ui-pericial", "frontend-design", "design-motion-principles"]
    assert ordinary[:4] == MANIFEST["material_bundle"]
    assert "impeccable" not in ordinary
    assert "impeccable" in route(MANIFEST, profiles=["ui"], conditions={"polish_requested"}, material=True, repository_mutation=True)["ordered_skills"]


def test_stage_gates_and_terminal_review_are_explicit():
    case = route(MANIFEST, profiles=["case_analysis"], conditions={"material_claims"}, material=True)["ordered_skills"]
    assert "motor-vicios-construtivos" not in case and "redacao-laudo-pericial" not in case
    assurance = route(MANIFEST, profiles=["assurance"], conditions={"systemic_risk"}, material=True)["ordered_skills"]
    assert assurance == ["systemic-auditor"] and "test-driven-development" not in assurance
    claims = route(MANIFEST, profiles=["case_analysis"], conditions={"material_claims"}, material=True)["ordered_skills"]
    assert "auditoria-grounding-pericial" in claims and "test-driven-development" not in claims


def test_unknown_material_context_fails_closed_and_schema_rejects_execution_fields():
    assert route(MANIFEST, profiles=["unknown"], conditions=set(), material=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=[], conditions=set(), material=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=[], conditions=set(), material=False, repository_mutation=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=["unknown"], conditions=set(), material=False, repository_mutation=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=["engineering"], conditions={"terminal_head"}, material=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=["ui"], conditions={"material_claims"}, material=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=["assurance"], conditions={"external_review_eligible"}, material=True)["status"] == "UNMAPPED_SKILL_CONTEXT"
    assert route(MANIFEST, profiles=["assurance"], conditions={"external_review_eligible"}, material=False)["status"] == "UNMAPPED_SKILL_CONTEXT"
    terminal_external = route(MANIFEST, profiles=["assurance"], conditions={"terminal_head", "external_review_eligible"}, material=True)
    assert terminal_external["status"] == "PASS" and "external-diversity-review" in terminal_external["ordered_skills"]
    poisoned = json.loads(json.dumps(MANIFEST)); poisoned["profiles"]["engineering"]["command"] = "run"
    schema = json.loads((ROOT / "schemas/skill-router-v3.schema.json").read_text(encoding="utf-8"))
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(poisoned))
    reordered = json.loads(json.dumps(MANIFEST)); reordered["precedence"][1:3] = reversed(reordered["precedence"][1:3])
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(reordered))
    no_prerequisites = json.loads(json.dumps(MANIFEST)); no_prerequisites["condition_requires"] = {}
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(no_prerequisites))
