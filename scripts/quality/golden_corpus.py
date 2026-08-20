"""Golden Forensic Corpus V1: replay-verifies hotspot entrypoints against frozen golden cases.

Part of POST_TOOLING_MAINTAINABILITY_SEQUENCE_V1 Stage 2
(docs/stabilization/golden-forensic-corpus-v1-design.md). Detects semantic
drift across the 5 hotspots named in docs/stabilization/hotspot-characterization-v1.md
before MAINTAINABILITY_REFACTORING_V1 touches them. Deterministic, first-party,
synthetic -- no real case data (NO_REAL_CASE_PRIVATE_DATA).

Each case declares WHY it exists (purpose, expected_provenance/classifications/
warnings/inconclusivity, invariants_exercised) in addition to its raw
expected_output, so a drift finding names the broken invariant/case, not just
"JSON differs" -- this matters most once MAINTAINABILITY_REFACTORING_V1 starts
touching these entrypoints.

This module is intentionally domain-agnostic: the QUALITY component
(scripts/quality/, layer GOVERNANCE) is only allowed to depend on AGENTIC
(config/architecture-policy-v1.json) -- it may not import DOMAIN-layer
hotspot modules (MOTOR/TRIAGE/INSPECTION/PJE). The per-hotspot adapters that
actually call motor.executar/gerar_vistoria/gerar_delimitacao/
validar_integridade/autocorrigir live in tests/test_golden_forensic_corpus_v1.py
instead (tests/ sits outside productionRoots, matching every other test
file's existing pattern of importing domain code directly) and are passed
in via the `adapters` parameter.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_MARKER = "referencias/privadas"
STATUSES = {"APPROVED", "CHARACTERIZED_NOT_APPROVED", "KNOWN_BUG"}
MODES = {"EXACT", "RAISES"}
COVERAGE_ELIGIBLE_STATUSES = {"APPROVED"}


def _finding(case_id: str, hotspot_id: str, reason: str, detail: str, invariant: str = "GOLDEN_CORPUS_FIDELITY", severity: str = "P1") -> dict:
    return {"invariant": invariant, "boundary": "QUALITY_GATE", "teste": f"{hotspot_id}::{case_id}", "motivo": reason, "severidade": severity, "detalhe": detail}


def _pop_path(payload: Any, dotted: str) -> None:
    parts = dotted.split(".")
    node = payload
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def _canonical(payload: Any, ignored: list[str]) -> str:
    cleaned = copy.deepcopy(payload)
    for path in ignored:
        _pop_path(cleaned, path)
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _materialize(root: Path, layout: dict) -> None:
    for relative, content in layout.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


SEMANTIC_FAMILIES = {
    "allegations", "documentary_evidence", "observations", "measurements",
    "technical_inference", "inconclusive_findings", "contradictory_evidence",
    "normative_references", "provenance", "professional_override",
    "source_value", "engine_decision", "ai_proposal_not_effective_alone",
    "absent_information", "unverifiable_information", "not_observed",
    "correction_persistence", "deterministic_replay", "reordered_inputs",
    "duplicate_inputs", "equivalent_input_representations",
}

REQUIRED_UNREACHABLE_KEYS = {"location", "reachability_today", "latent_defect", "golden_execution_case", "reason"}


def load_corpus(root: Path = ROOT) -> list[dict]:
    registry = json.loads((root / "tests/fixtures/core-fixtures.json").read_text(encoding="utf-8"))
    files = sorted(item["arquivo"] for item in registry.get("fixtures", []) if str(item.get("dominio", "")).startswith("GOLDEN_CORPUS"))
    corpora = []
    for relative in files:
        corpora.append(json.loads((root / relative).read_text(encoding="utf-8")))
    return corpora


def _run_case(case: dict, hotspot_id: str, adapter: Callable[[dict], Any]) -> list[dict]:
    case_id = case.get("case_id", "UNKNOWN")
    purpose = case.get("purpose", "")
    findings: list[dict] = []
    status = case.get("status")
    if status not in STATUSES:
        return [_finding(case_id, hotspot_id, "STATUS_INVALIDO", str(status))]
    mode = case.get("expected_output_mode")
    if mode not in MODES:
        return [_finding(case_id, hotspot_id, "MODO_INVALIDO", str(mode))]
    if not case.get("semantic_families"):
        findings.append(_finding(case_id, hotspot_id, "SEMANTIC_FAMILIES_VAZIO", "caso sem semantic_families declarada"))
    if not case.get("invariants_exercised"):
        findings.append(_finding(case_id, hotspot_id, "INVARIANTS_EXERCISED_VAZIO", "caso sem invariants_exercised declarado"))
    if not purpose:
        findings.append(_finding(case_id, hotspot_id, "PURPOSE_VAZIO", "caso sem purpose declarado -- corpus não pode virar apenas um diff cego"))
    invariant = ",".join(case.get("invariants_exercised") or []) or "GOLDEN_CORPUS_FIDELITY"
    ignored = case.get("non_semantic_fields_ignored", [])
    case_input = case.get("input", {})

    try:
        actual = adapter(copy.deepcopy(case_input))
    except Exception as exc:  # noqa: BLE001 -- comparison target, not a swallow
        if mode == "RAISES":
            spec = case.get("expected_output", {}).get("raises", {})
            if type(exc).__name__ != spec.get("type"):
                findings.append(_finding(case_id, hotspot_id, "RAISES_TIPO_DIVERGENTE", f"{purpose} -- esperado {spec.get('type')}, obtido {type(exc).__name__}", invariant))
            elif spec.get("message_contains") and spec["message_contains"] not in str(exc):
                findings.append(_finding(case_id, hotspot_id, "RAISES_MENSAGEM_DIVERGENTE", f"{purpose} -- '{spec['message_contains']}' ausente em '{exc}'", invariant))
        else:
            findings.append(_finding(case_id, hotspot_id, "EXCECAO_NAO_ESPERADA", f"{purpose} -- {type(exc).__name__}: {exc}", invariant))
        return findings

    if mode == "RAISES":
        findings.append(_finding(case_id, hotspot_id, "RAISES_NAO_OCORREU", f"{purpose} -- adapter retornou normalmente onde uma exceção era esperada", invariant))
        return findings

    expected = case.get("expected_output")
    if _canonical(actual, ignored) != _canonical(expected, ignored):
        findings.append(_finding(case_id, hotspot_id, "GOLDEN_OUTPUT_DIVERGENTE", f"{purpose} -- saída atual diverge do golden registrado (invariante exercido: {invariant})", invariant))

    if case.get("check_deterministic_replay"):
        try:
            replay = adapter(copy.deepcopy(case_input))
        except Exception as exc:  # noqa: BLE001
            findings.append(_finding(case_id, hotspot_id, "REPLAY_EXCECAO", f"{purpose} -- {type(exc).__name__}: {exc}", "IDEMPOTENCE"))
        else:
            if _canonical(actual, ignored) != _canonical(replay, ignored):
                findings.append(_finding(case_id, hotspot_id, "REPLAY_NAO_DETERMINISTICO", f"{purpose} -- duas execuções independentes do mesmo input produziram saídas distintas", "IDEMPOTENCE"))
    return findings


def _check_no_real_case_private_data(corpus: dict, hotspot_id: str) -> list[dict]:
    serialized = json.dumps(corpus, ensure_ascii=False)
    if PRIVATE_MARKER in serialized:
        return [_finding("*", hotspot_id, "NO_REAL_CASE_PRIVATE_DATA", f"corpus contém referência a '{PRIVATE_MARKER}'", severity="P0")]
    return []


def _check_known_unreachable(corpus: dict, hotspot_id: str) -> list[dict]:
    findings = []
    for entry in corpus.get("known_unreachable", []):
        missing = REQUIRED_UNREACHABLE_KEYS - set(entry)
        if missing:
            findings.append(_finding("*", hotspot_id, "KNOWN_UNREACHABLE_INCOMPLETO", f"campos ausentes {sorted(missing)} em {entry}"))
        elif entry.get("golden_execution_case") is not None and entry.get("reachability_today") is False:
            findings.append(_finding("*", hotspot_id, "KNOWN_UNREACHABLE_INCONSISTENTE", "reachability_today=false mas golden_execution_case não é null"))
        elif entry.get("reachability_today") is True and entry.get("golden_execution_case") is None:
            findings.append(_finding("*", hotspot_id, "KNOWN_UNREACHABLE_INCONSISTENTE", "reachability_today=true mas golden_execution_case é null -- caminho alcançável sem nenhum caso golden pinando-o"))
    return findings


def validate_golden_corpus(root: Path = ROOT, *, adapters: dict[str, Callable[[dict], Any]]) -> list[dict]:
    findings: list[dict] = []
    for corpus in load_corpus(root):
        hotspot_id = corpus.get("hotspot_id", "UNKNOWN")
        findings.extend(_check_no_real_case_private_data(corpus, hotspot_id))
        findings.extend(_check_known_unreachable(corpus, hotspot_id))
        adapter = adapters.get(hotspot_id)
        if adapter is None:
            findings.append(_finding("*", hotspot_id, "HOTSPOT_SEM_ADAPTER", "nenhum adapter registrado para este hotspot_id"))
            continue
        for case in corpus.get("cases", []):
            findings.extend(_run_case(case, hotspot_id, adapter))
        for entry in corpus.get("not_applicable", []):
            if not entry.get("hotspot_id") or not entry.get("family") or not entry.get("reason"):
                findings.append(_finding("*", hotspot_id, "NOT_APPLICABLE_INCOMPLETO", str(entry)))
    return findings


def build_coverage_map(root: Path = ROOT) -> dict:
    matrix: dict[str, dict[str, list[str]]] = {family: {} for family in sorted(SEMANTIC_FAMILIES)}
    not_applicable: dict[tuple[str, str], str] = {}
    known_unreachable: list[dict] = []
    hotspot_ids: list[str] = []
    for corpus in load_corpus(root):
        hotspot_id = corpus.get("hotspot_id", "UNKNOWN")
        hotspot_ids.append(hotspot_id)
        for case in corpus.get("cases", []):
            if case.get("status") not in COVERAGE_ELIGIBLE_STATUSES:
                continue
            for family in case.get("semantic_families", []):
                matrix.setdefault(family, {}).setdefault(hotspot_id, []).append(case["case_id"])
        for entry in corpus.get("not_applicable", []):
            not_applicable[(entry["hotspot_id"], entry["family"])] = entry["reason"]
        for entry in corpus.get("known_unreachable", []):
            known_unreachable.append({"hotspot_id": hotspot_id, **entry})
    hotspot_ids = sorted(set(hotspot_ids))
    return {"hotspots": hotspot_ids, "matrix": matrix, "not_applicable": not_applicable, "known_unreachable": known_unreachable}


def render_coverage_map(coverage: dict) -> str:
    hotspots = coverage["hotspots"]
    lines = ["# Golden Forensic Corpus V1 -- Coverage Map", "", "Gerado por `python -m scripts.quality.golden_corpus --coverage-map`. Não editar manualmente.", "", "Apenas casos com `status: APPROVED` contam para a cobertura abaixo. Casos `CHARACTERIZED_NOT_APPROVED`/`KNOWN_BUG` continuam pinados (qualquer drift ainda quebra o gate), mas ficam fora da contagem de cobertura -- ver docs/stabilization/hotspot-characterization-v1.md e o próprio corpus para o detalhe de cada um.", "", "| Família semântica | " + " | ".join(hotspots) + " |", "| --- | " + " | ".join("---" for _ in hotspots) + " |"]
    for family in sorted(coverage["matrix"]):
        row = [family]
        for hotspot_id in hotspots:
            cases = coverage["matrix"][family].get(hotspot_id)
            if cases:
                row.append(", ".join(sorted(cases)))
            elif (hotspot_id, family) in coverage["not_applicable"]:
                row.append("N/A")
            else:
                row.append("")
        lines.append("| " + " | ".join(row) + " |")
    if coverage["known_unreachable"]:
        lines += ["", "## Caminhos conhecidos como inalcançáveis hoje (sem caso golden)", ""]
        for entry in coverage["known_unreachable"]:
            lines.append(f"- **{entry['hotspot_id']}** `{entry['location']}` -- `latent_defect={entry['latent_defect']}`, `golden_execution_case={entry['golden_execution_case']}`. {entry['reason']}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Golden Forensic Corpus V1 utilities. This module cannot execute the "
            "hotspot entrypoints itself (GOVERNANCE/QUALITY may not import DOMAIN "
            "modules, config/architecture-policy-v1.json). To actually verify the "
            "corpus against real behavior, run: pytest tests/test_golden_forensic_corpus_v1.py"
        )
    )
    parser.add_argument("--coverage-map", action="store_true", help="Render the semantic-family x hotspot coverage map to stdout.")
    args = parser.parse_args(argv)
    if args.coverage_map:
        sys.stdout.write(render_coverage_map(build_coverage_map()))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
