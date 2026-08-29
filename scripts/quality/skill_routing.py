"""Pure deterministic selector for SKILL_ROUTING_V3."""
from __future__ import annotations


def route(manifest: dict, *, profiles: list[str], conditions: set[str], material: bool,
          repository_mutation: bool = False) -> dict:
    configured = manifest.get("profiles", {})
    unknown = sorted(set(profiles) - set(configured))
    selected = [configured[name] for name in profiles if name in configured]
    known_conditions = {name for profile in selected for name in profile["conditional"]}
    unknown_conditions = sorted(conditions - known_conditions)
    missing_requirements = sorted({required for condition in conditions for required in manifest.get("condition_requires", {}).get(condition, []) if required not in conditions})
    if missing_requirements or ((material or repository_mutation) and (not profiles or unknown or unknown_conditions)):
        return {"status": "UNMAPPED_SKILL_CONTEXT", "ordered_skills": [], "reasons": unknown + unknown_conditions + missing_requirements}
    ordered: list[str] = []
    reasons: list[dict] = []
    if repository_mutation:
        for skill in manifest["material_bundle"]:
            ordered.append(skill); reasons.append({"skill": skill, "reason": "global:material"})
    for profile_name in profiles:
        profile = configured.get(profile_name)
        if profile is None:
            continue
        selections = [("required", profile["required"])]
        selections.extend((condition, profile["conditional"].get(condition, [])) for condition in sorted(conditions))
        for reason, skills in selections:
            for skill in skills:
                if skill not in ordered:
                    ordered.append(skill); reasons.append({"skill": skill, "reason": f"{profile_name}:{reason}"})
    return {"status": "PASS", "ordered_skills": ordered, "reasons": reasons}
