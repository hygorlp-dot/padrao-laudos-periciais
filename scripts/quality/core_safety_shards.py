"""Particionamento determinístico do regression e agregador closed-set (V7-4A, #259).

Nada aqui executa testes nem processos. O módulo:

* valida o manifest versionado ``config/core-safety-shards-v1.json``;
* deriva, a partir do comando ``regression`` do próprio ``verify_core`` (via
  ``core_safety_plan``), o argv de cada shard e o ``--ignore`` da partição que
  permanece dentro do ``verify_core``;
* grava evidência por job (SHA exato, inventário de node IDs, coverage);
* agrega, falhando fechado, o conjunto completo de provas do ``core-safety``.

A partição que fica no ``verify_core`` (``gate``) é o COMPLEMENTO dos shards:
arquivo de teste novo nunca some, cai automaticamente no gate. Shards só podem
conter arquivos cuja coverage medida já está contida na do gate; isso é provado
a cada execução (``PARTITION_COVERAGE_DRIFT``), não presumido.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import core_safety_plan
from .metrics import analyze_complexity, parse_coverage_totals, validate_quality_baseline

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "config/core-safety-shards-v1.json"
MANIFEST_ID = "CORE_SAFETY_REGRESSION_SHARDS_V1"
ARCHITECTURE_SUITE = "tests/test_architecture_analyzer_v1.py"
NODES_PLUGIN = "scripts.quality.core_safety_nodes"
GATE_SCHEMA = "CORE_SAFETY_GATE_EVIDENCE_V1"
SHARD_SCHEMA = "CORE_SAFETY_SHARD_EVIDENCE_V1"
INVENTORY_SCHEMA = "CORE_SAFETY_INVENTORY_EVIDENCE_V1"
NODE_REPORT_SCHEMA = "CORE_SAFETY_NODE_REPORT_V1"
GATE_DATA = "coverage-quality-v2.data"
REQUIRED_JOBS = ("architecture", "core-gate", "inventory", "regression-shard")
EXPECTED_GATE_CHECKS = (
    "invariants", "fixtures", "privacy", "property tests", "gate tests", "compileall",
    "historical critical mutation suite", "quality V2", "schemas", "E2E positive",
    "E2E negative", "capability cutover tests", "regression", "coverage report",
    "diff check", "quality non-regression",
)
TIMING_ONLY_CODE = "FULL_GATE_DURATION_REGRESSION"
_SHARD_ID = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHECK_LINE = re.compile(r"^\[(PASS|FAIL)\] (.+)$")


class ShardError(RuntimeError):
    """Evidência ou manifest inválido: o chamador deve falhar fechado."""


# --------------------------------------------------------------------- manifest

def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(root: Path = ROOT) -> dict:
    return json.loads((root / MANIFEST_PATH).read_text(encoding="utf-8"))


def regression_argv(root: Path = ROOT) -> list[str]:
    return list(core_safety_plan.stage("regression", core_safety_plan.gate_plan("full", root)).argv)


def _pytest_tail(argv: list[str]) -> list[str]:
    """Argumentos do pytest dentro do comando ``coverage run ... -m pytest ...``."""
    positions = [index for index in range(len(argv) - 1) if argv[index] == "-m" and argv[index + 1] == "pytest"]
    if len(positions) != 1:
        raise ShardError("comando regression sem um único '-m pytest'")
    tail = argv[positions[0] + 2:]
    if tail.count("tests") != 1:
        raise ShardError("comando regression deve ter exatamente um alvo posicional 'tests'")
    return tail


def regression_ignores(argv: list[str]) -> set[str]:
    return {item.split("=", 1)[1] for item in _pytest_tail(argv) if item.startswith("--ignore=")}


def regression_test_files(root: Path = ROOT, argv: list[str] | None = None) -> list[str]:
    """Arquivos que o regression integral do ``core-safety`` atual coleta.

    Inclui a exclusão de arquitetura que a CI aplica via ``PYTEST_ADDOPTS``.
    """
    argv = regression_argv(root) if argv is None else argv
    ignored = regression_ignores(argv) | {ARCHITECTURE_SUITE}
    files = {
        path.relative_to(root).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in (root / "tests").rglob(pattern)
        if "__pycache__" not in path.parts
    }
    return sorted(files - ignored)


def validate_manifest(manifest: dict, root: Path = ROOT, argv: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(manifest, dict) or manifest.get("manifestId") != MANIFEST_ID:
        return ["MANIFEST_ID_INVALID"]
    if manifest.get("schemaVersion") != "1.0.0":
        errors.append("MANIFEST_SCHEMA_VERSION_INVALID")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        return errors + ["MANIFEST_SHARDS_MISSING"]
    regression = set(regression_test_files(root, argv))
    seen_ids: set[str] = set()
    owner: dict[str, str] = {}
    for shard in shards:
        shard_id = shard.get("id") if isinstance(shard, dict) else None
        if not isinstance(shard_id, str) or not _SHARD_ID.match(shard_id) or shard_id == "gate":
            errors.append(f"SHARD_ID_INVALID:{shard_id!r}")
            continue
        if shard_id in seen_ids:
            errors.append(f"SHARD_ID_DUPLICATED:{shard_id}")
        seen_ids.add(shard_id)
        files = shard.get("files")
        if not isinstance(files, list) or not files:
            errors.append(f"SHARD_EMPTY:{shard_id}")
            continue
        if files != sorted(files):
            errors.append(f"SHARD_FILES_NOT_SORTED:{shard_id}")
        for path in files:
            if not isinstance(path, str) or path not in regression:
                errors.append(f"SHARD_FILE_NOT_IN_REGRESSION:{shard_id}:{path!r}")
            elif path in owner:
                errors.append(f"SHARD_FILE_DUPLICATED:{path}:{owner[path]}:{shard_id}")
            else:
                owner[path] = shard_id
    if regression and not regression - set(owner):
        errors.append("GATE_PARTITION_EMPTY")
    return errors


def shard_files(manifest: dict, shard_id: str) -> list[str]:
    matches = [shard for shard in manifest["shards"] if shard.get("id") == shard_id]
    if len(matches) != 1:
        raise ShardError(f"shard {shard_id!r} ausente ou repetido no manifest")
    return list(matches[0]["files"])


def offloaded_files(manifest: dict) -> list[str]:
    return sorted(path for shard in manifest["shards"] for path in shard["files"])


def gate_files(manifest: dict, root: Path = ROOT, argv: list[str] | None = None) -> list[str]:
    return sorted(set(regression_test_files(root, argv)) - set(offloaded_files(manifest)))


def gate_addopts(manifest: dict) -> str:
    """``--ignore`` adicional do verify_core: só poda varredura de diretório.

    ``--ignore`` não remove caminho explícito (estágios E2E, quality V2 e as
    execuções internas da mutation suite continuam íntegros) e nunca filtra por
    ``-k``/``-m``/``--deselect``.
    """
    return " ".join(f"--ignore={path}" for path in offloaded_files(manifest))


def shard_argv(manifest: dict, shard_id: str, *, data_file: str, nodes_file: str,
               root: Path = ROOT, argv: list[str] | None = None) -> list[str]:
    """argv do shard: o MESMO comando regression do juiz, com outro alvo e outro data file."""
    argv = regression_argv(root) if argv is None else list(argv)
    _pytest_tail(argv)
    data_flags = [index for index, item in enumerate(argv) if item.startswith("--data-file=")]
    if len(data_flags) != 1:
        raise ShardError("comando regression sem um único --data-file")
    argv[data_flags[0]] = f"--data-file={data_file}"
    target = len(argv) - 1 - argv[::-1].index("tests")
    files = shard_files(manifest, shard_id)
    return argv[:target] + files + argv[target + 1:] + ["-p", NODES_PLUGIN, f"--core-safety-nodes={nodes_file}"]


def collect_argv(manifest: dict, partition: str, *, nodes_file: str, python: str = sys.executable,
                 root: Path = ROOT, argv: list[str] | None = None) -> list[str]:
    """Coleta (sem execução) do regression integral (``full``) ou da partição ``gate``."""
    argv = regression_argv(root) if argv is None else argv
    tail = _pytest_tail(argv) + [f"--ignore={ARCHITECTURE_SUITE}"]
    if partition == "gate":
        tail += gate_addopts(manifest).split()
    elif partition != "full":
        raise ShardError(f"partição desconhecida: {partition!r}")
    return [python, "-m", "pytest", *tail, "--collect-only", "-p", NODES_PLUGIN, f"--core-safety-nodes={nodes_file}"]


# --------------------------------------------------------------------- evidence

def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ShardError(f"evidência ilegível: {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ShardError(f"evidência malformada: {path.name}")
    return payload


def _node_report(payload: object, *, collect_only: bool, label: str) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != NODE_REPORT_SCHEMA:
        raise ShardError(f"{label}: relatório de nodes malformado")
    if payload.get("collect_only") is not collect_only:
        raise ShardError(f"{label}: modo de coleta inesperado")
    collected = payload.get("collected")
    if not isinstance(collected, list) or not collected or not all(isinstance(item, str) for item in collected):
        raise ShardError(f"{label}: inventário de nodes vazio ou malformado")
    if len(set(collected)) != len(collected):
        raise ShardError(f"{label}: node ID repetido no inventário")
    if payload.get("exitstatus") != 0:
        raise ShardError(f"{label}: pytest terminou com exitstatus {payload.get('exitstatus')!r}")
    return payload


def write_shard_evidence(target: Path, *, shard_id: str, sha: str, exit_code: int, seconds: float,
                         nodes_file: Path, data_file: Path, root: Path = ROOT) -> dict:
    nodes = json.loads(nodes_file.read_text(encoding="utf-8")) if nodes_file.is_file() else None
    payload = {
        "schema": SHARD_SCHEMA, "shard": shard_id, "sha": sha, "exit_code": int(exit_code),
        "seconds": round(float(seconds), 3), "manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "nodes": nodes, "coverage_file": data_file.name,
        "coverage_sha256": sha256_file(data_file) if data_file.is_file() else None,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def write_gate_evidence(target: Path, *, sha: str, exit_code: int, report: Path, data_file: Path,
                        root: Path = ROOT) -> dict:
    payload = {
        "schema": GATE_SCHEMA, "sha": sha, "exit_code": int(exit_code),
        "manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "report": report.read_text(encoding="utf-8", errors="replace") if report.is_file() else None,
        "coverage_file": data_file.name,
        "coverage_sha256": sha256_file(data_file) if data_file.is_file() else None,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def write_inventory_evidence(target: Path, *, sha: str, full_nodes: Path, gate_nodes: Path,
                             root: Path = ROOT) -> dict:
    def read(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    payload = {
        "schema": INVENTORY_SCHEMA, "sha": sha, "manifest_sha256": sha256_file(root / MANIFEST_PATH),
        "full": read(full_nodes), "gate": read(gate_nodes),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def parse_gate_report(report: str) -> dict:
    """Interpreta a saída do ``verify_core`` sem reinterpretar a política dele."""
    checks: list[tuple[str, bool]] = []
    result = None
    timing = None
    findings: list[str] = []
    in_findings = False
    for line in report.splitlines():
        line = line.rstrip()
        match = _CHECK_LINE.match(line)
        if match:
            checks.append((match.group(2), match.group(1) == "PASS"))
        elif line.startswith("RESULT: "):
            result = line.removeprefix("RESULT: ").strip()
            in_findings = True
        elif line.startswith("TIMING_STATUS = "):
            timing = line.removeprefix("TIMING_STATUS = ").strip()
        elif line.startswith("DURATION_SECONDS:"):
            in_findings = False
        elif in_findings and line:
            findings.append(line)
    return {"checks": checks, "result": result, "timing_status": timing, "findings": findings}


def semantic_status(parsed: dict) -> str:
    """PASS só quando todo check é PASS, exceto uma falha exclusivamente temporal."""
    names = [name for name, _ok in parsed["checks"]]
    if tuple(names) != EXPECTED_GATE_CHECKS:
        return "FAIL"
    failing = [name for name, ok in parsed["checks"] if not ok]
    if not failing:
        return "PASS" if parsed["result"] == "PASS" else "FAIL"
    timing_only = (
        failing == ["quality non-regression"]
        and parsed["findings"]
        and all(TIMING_ONLY_CODE in item and "QUALITY_NON_REGRESSION" in item for item in parsed["findings"])
    )
    return "PASS" if timing_only else "FAIL"


# --------------------------------------------------------------------- coverage

def _coverage_sets(data_file: Path) -> tuple[set, set]:
    from coverage import CoverageData

    if not data_file.is_file():
        raise ShardError(f"coverage ausente: {data_file.name}")
    data = CoverageData(str(data_file))
    data.read()
    # Shard que não mede nenhum --source tem data vazio (nada a vazar); data
    # com arquivos medidos, porém sem arcs, não prova branch coverage.
    if data.measured_files() and not data.has_arcs():
        raise ShardError(f"coverage sem branch/arcs: {data_file.name}")
    lines = {(path, line) for path in data.measured_files() for line in (data.lines(path) or ())}
    arcs = {(path, arc) for path in data.measured_files() for arc in (data.arcs(path) or ())}
    return lines, arcs


def combined_coverage_totals(gate_data: Path, shard_data: list[Path], root: Path, workdir: Path) -> dict:
    from coverage import Coverage

    combined = workdir / "coverage-core-safety-combined.data"
    report = workdir / "coverage-core-safety-combined.json"
    for stale in (combined, report):
        if stale.exists():
            stale.unlink()
    coverage = Coverage(data_file=str(combined), branch=True)
    coverage.combine([str(path) for path in (gate_data, *shard_data)], strict=True, keep=True)
    coverage.save()
    coverage.json_report(outfile=str(report))
    return parse_coverage_totals(json.loads(report.read_text(encoding="utf-8")))


# --------------------------------------------------------------------- aggregator

def aggregate(evidence_dir: Path, *, sha: str, needs: dict, root: Path = ROOT,
              workdir: Path | None = None, argv: list[str] | None = None) -> dict:
    """Reconstrói e valida o conjunto fechado de provas. Qualquer lacuna = FAIL."""
    errors: list[str] = []
    rows: list[tuple[str, bool, str]] = []
    workdir = evidence_dir if workdir is None else workdir

    def fail(code: str) -> None:
        errors.append(code)

    if not _SHA.match(sha or ""):
        fail("CANDIDATE_SHA_INVALID")
    # 1. todo job obrigatório concluiu com sucesso (skipped/cancelled/failure = FAIL)
    if not isinstance(needs, dict):
        needs = {}
    for job in REQUIRED_JOBS:
        result = (needs.get(job) or {}).get("result") if isinstance(needs.get(job), dict) else None
        if result != "success":
            fail(f"JOB_NOT_SUCCESSFUL:{job}:{result}")
    for job in sorted(set(needs) - set(REQUIRED_JOBS)):
        fail(f"JOB_UNEXPECTED:{job}")

    # 2. manifest atual válido
    try:
        manifest = load_manifest(root)
        manifest_errors = validate_manifest(manifest, root, argv)
        manifest_sha = sha256_file(root / MANIFEST_PATH)
    except (OSError, ValueError, ShardError, KeyError, TypeError) as exc:
        manifest, manifest_errors, manifest_sha = None, [f"MANIFEST_UNREADABLE:{exc}"], None
    errors.extend(manifest_errors)
    shard_ids = [shard["id"] for shard in manifest["shards"]] if manifest and not manifest_errors else []

    def bound(payload: dict, label: str, schema: str) -> bool:
        ok = True
        if payload.get("schema") != schema:
            fail(f"EVIDENCE_SCHEMA_INVALID:{label}"); ok = False
        if payload.get("sha") != sha:
            fail(f"EVIDENCE_SHA_MISMATCH:{label}"); ok = False
        if payload.get("manifest_sha256") != manifest_sha:
            fail(f"EVIDENCE_MANIFEST_MISMATCH:{label}"); ok = False
        return ok

    # 3. gate (verify_core com a partição complementar)
    gate_parsed = {"checks": [], "result": None, "timing_status": None, "findings": []}
    gate_data = evidence_dir / "gate" / GATE_DATA
    try:
        gate = _load_json(evidence_dir / "gate" / "gate-evidence.json")
        if bound(gate, "gate", GATE_SCHEMA):
            if not isinstance(gate.get("report"), str):
                fail("GATE_REPORT_MISSING")
            else:
                gate_parsed = parse_gate_report(gate["report"])
                if tuple(name for name, _ in gate_parsed["checks"]) != EXPECTED_GATE_CHECKS:
                    fail("GATE_CHECK_SET_NOT_CLOSED")
            if gate.get("exit_code") != 0 or gate_parsed["result"] != "PASS":
                fail(f"GATE_NOT_PASS:{gate.get('exit_code')!r}:{gate_parsed['result']!r}")
            if gate.get("coverage_file") != GATE_DATA or not gate_data.is_file() \
                    or sha256_file(gate_data) != gate.get("coverage_sha256"):
                fail("GATE_COVERAGE_IDENTITY_MISMATCH")
    except ShardError as exc:
        fail(f"GATE_EVIDENCE_INVALID:{exc}")

    # 4. inventário de referência
    full_nodes: set[str] = set()
    gate_nodes: set[str] = set()
    try:
        inventory = _load_json(evidence_dir / "inventory" / "inventory-evidence.json")
        if bound(inventory, "inventory", INVENTORY_SCHEMA):
            full_nodes = set(_node_report(inventory.get("full"), collect_only=True, label="inventory.full")["collected"])
            gate_nodes = set(_node_report(inventory.get("gate"), collect_only=True, label="inventory.gate")["collected"])
    except ShardError as exc:
        fail(f"INVENTORY_INVALID:{exc}")
    if manifest and not manifest_errors and gate_nodes:
        allowed_gate = set(gate_files(manifest, root, argv))
        stray = sorted({node.split("::", 1)[0] for node in gate_nodes} - allowed_gate)
        if stray:
            fail(f"GATE_PARTITION_HAS_OFFLOADED_FILE:{stray[:5]}")

    # 5. shards: presença exata, identidade, resultado, inventário executado
    shard_dirs = sorted(path for path in evidence_dir.glob("shard-*") if path.is_dir())
    present = {path.name.removeprefix("shard-") for path in shard_dirs}
    for missing in sorted(set(shard_ids) - present):
        fail(f"SHARD_MISSING:{missing}")
    for extra in sorted(present - set(shard_ids)):
        fail(f"SHARD_UNEXPECTED:{extra}")
    executed: dict[str, set[str]] = {}
    shard_data: list[Path] = []
    for shard_id in shard_ids:
        if shard_id not in present:
            continue
        label = f"shard:{shard_id}"
        before = len(errors)
        try:
            payload = _load_json(evidence_dir / f"shard-{shard_id}" / "shard-evidence.json")
            if not bound(payload, label, SHARD_SCHEMA) or payload.get("shard") != shard_id:
                fail(f"SHARD_IDENTITY_INVALID:{shard_id}")
                continue
            if payload.get("exit_code") != 0:
                fail(f"SHARD_FAILED:{shard_id}:{payload.get('exit_code')!r}")
            report = _node_report(payload.get("nodes"), collect_only=False, label=label)
            collected = set(report["collected"])
            outcomes = report.get("outcomes") or {}
            if set(outcomes) != collected:
                fail(f"SHARD_NODES_NOT_ALL_EXECUTED:{shard_id}")
            bad = sorted(node for node, outcome in outcomes.items() if outcome not in {"passed", "skipped"})
            if bad:
                fail(f"SHARD_NODES_FAILED:{shard_id}:{bad[:5]}")
            files = set(shard_files(manifest, shard_id))
            outside = sorted({node.split("::", 1)[0] for node in collected} - files)
            if outside:
                fail(f"SHARD_RAN_FOREIGN_FILES:{shard_id}:{outside[:5]}")
            empty = sorted(files - {node.split("::", 1)[0] for node in collected})
            if empty:
                fail(f"SHARD_FILES_WITHOUT_NODES:{shard_id}:{empty[:5]}")
            data = evidence_dir / f"shard-{shard_id}" / str(payload.get("coverage_file") or "")
            if payload.get("coverage_file") != f"shard-{shard_id}.data" or not data.is_file() \
                    or sha256_file(data) != payload.get("coverage_sha256"):
                fail(f"SHARD_COVERAGE_IDENTITY_MISMATCH:{shard_id}")
            else:
                shard_data.append(data)
            executed[shard_id] = collected
            skipped = sum(1 for outcome in outcomes.values() if outcome == "skipped")
            rows.append((f"regression shard {shard_id}", len(errors) == before,
                         f"{len(collected)} nodes, {skipped} skipped, {payload.get('seconds')}s"))
        except ShardError as exc:
            fail(f"SHARD_EVIDENCE_INVALID:{shard_id}:{exc}")

    # 6. inventário: a coleta integral é a referência exata.
    #    Shards: node IDs executados == referência restrita aos seus arquivos.
    #    Gate: mesmo conjunto de arquivos e mesma contagem exata de nodes por
    #    arquivo. (IDs do gate são coletados em OUTRO processo; um teste cujo
    #    ID parametrizado embute bytes dependentes de relógio — ex.: zip com
    #    timestamp DOS — muda de ID entre processos sem mudar de node. Por isso
    #    o gate é provado por arquivo+contagem; shards, por ID exato.)
    def by_file(nodes: set[str]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for node in nodes:
            path = node.split("::", 1)[0]
            counts[path] = counts.get(path, 0) + 1
        return counts

    full_by_file = by_file(full_nodes)
    gate_by_file = by_file(gate_nodes)
    shard_file_set = {path for shard_id in shard_ids for path in shard_files(manifest, shard_id)} if shard_ids else set()
    expected_gate = {path: count for path, count in full_by_file.items() if path not in shard_file_set}
    mismatches: list[str] = []
    if gate_by_file != expected_gate:
        diff = sorted(set(gate_by_file.items()) ^ set(expected_gate.items()))
        mismatches.append(f"gate:{diff[:5]}")
    covered = sum(gate_by_file.values())
    overlaps: list[str] = []
    seen: set[str] = set()
    for shard_id in shard_ids:
        nodes = executed.get(shard_id)
        if nodes is None:
            continue
        overlaps.extend(sorted(seen & nodes)[:3])
        seen |= nodes
        expected = {node for node in full_nodes if node.split("::", 1)[0] in set(shard_files(manifest, shard_id))}
        if nodes != expected:
            mismatches.append(f"{shard_id}:missing={sorted(expected - nodes)[:3]}:extra={sorted(nodes - expected)[:3]}")
        covered += len(nodes)
    if overlaps:
        fail(f"NODE_INVENTORY_OVERLAP:{overlaps[:5]}")
    inventory_ok = bool(full_nodes) and not mismatches and not overlaps and covered == len(full_nodes) \
        and set(executed) == set(shard_ids) and bool(shard_ids)
    if not inventory_ok:
        fail(f"NODE_INVENTORY_MISMATCH:{mismatches[:5]}:covered={covered}:expected={len(full_nodes)}")
    rows.append(("node inventory", inventory_ok, f"{covered}/{len(full_nodes)} nodes"))

    # 7. coverage: shards ⊆ gate (equivalência ao regression integral) e não-regressão do combinado
    coverage_ok = False
    totals = None
    if gate_data.is_file() and len(shard_data) == len(shard_ids) and shard_ids:
        try:
            gate_lines, gate_arcs = _coverage_sets(gate_data)
            for data in shard_data:
                lines, arcs = _coverage_sets(data)
                if not lines <= gate_lines or not arcs <= gate_arcs:
                    fail(f"PARTITION_COVERAGE_DRIFT:{data.name}:{len(lines - gate_lines)}:{len(arcs - gate_arcs)}")
            totals = combined_coverage_totals(gate_data, shard_data, root, workdir)
            baseline = json.loads((root / "config/quality-baseline.json").read_text(encoding="utf-8"))
            complexity = analyze_complexity([root / item["path"] for item in baseline.get("hotspots", [])], base=root)
            for item in validate_quality_baseline(baseline, totals, complexity):
                fail(f"COMBINED_{item['code']}")
            coverage_ok = not [e for e in errors if e.startswith(("PARTITION_COVERAGE_DRIFT", "COMBINED_"))]
        except (ShardError, OSError, ValueError, KeyError, TypeError) as exc:
            fail(f"COMBINED_COVERAGE_INVALID:{exc}")
        except Exception as exc:  # coverage.exceptions.* (ex.: NoDataError): falhar fechado
            fail(f"COMBINED_COVERAGE_INVALID:{type(exc).__name__}:{exc}")
    else:
        fail("COMBINED_COVERAGE_INCOMPLETE")
    rows.append(("coverage partition equivalence", coverage_ok,
                 f"line={totals['line_percent']} branch={totals['branch_percent']}" if totals else "unavailable"))

    # 8. conjunto fechado reconstruído
    gate_checks = dict(gate_parsed["checks"])
    shards_ok = bool(shard_ids) and all(ok for name, ok, _ in rows if name.startswith("regression shard ")) \
        and len([r for r in rows if r[0].startswith("regression shard ")]) == len(shard_ids)
    closed: list[tuple[str, bool]] = []
    for name in EXPECTED_GATE_CHECKS:
        ok = gate_checks.get(name) is True
        if name == "regression":
            ok = ok and shards_ok and inventory_ok
        elif name in {"coverage report", "quality non-regression"}:
            ok = ok and coverage_ok
        closed.append((name, ok))
    semantic = semantic_status(gate_parsed) if gate_parsed["checks"] else "FAIL"
    if semantic == "PASS" and not (shards_ok and inventory_ok and coverage_ok):
        semantic = "FAIL"
    result = "PASS" if not errors and all(ok for _, ok in closed) and all(ok for _, ok, _ in rows) else "FAIL"
    return {
        "result": result, "semantic_status": semantic,
        "timing_status": gate_parsed["timing_status"] or "UNKNOWN",
        "checks": closed, "evidence": rows, "errors": errors,
    }


def print_aggregate(summary: dict) -> None:
    print("CORE SAFETY GATE\n")
    for name, ok in summary["checks"]:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print("\nEVIDENCE")
    for name, ok, detail in summary["evidence"]:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} ({detail})")
    print(f"\nSEMANTIC_STATUS = {summary['semantic_status']}")
    print(f"TIMING_STATUS = {summary['timing_status']}")
    print(f"RESULT: {summary['result']}")
    for error in summary["errors"]:
        print(f"FINDING {error}")


# --------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="core-safety sharding (V7-4A)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("gate-addopts")
    sub.add_parser("shard-ids")
    p = sub.add_parser("shard-argv"); p.add_argument("--shard", required=True)
    p.add_argument("--data-file", required=True); p.add_argument("--nodes-file", required=True)
    p = sub.add_parser("collect-argv"); p.add_argument("--partition", required=True)
    p.add_argument("--nodes-file", required=True)
    p = sub.add_parser("shard-evidence")
    for flag in ("--shard", "--sha", "--exit-code", "--seconds", "--nodes-file", "--data-file", "--out"):
        p.add_argument(flag, required=True)
    p = sub.add_parser("gate-evidence")
    for flag in ("--sha", "--exit-code", "--report", "--data-file", "--out"):
        p.add_argument(flag, required=True)
    p = sub.add_parser("inventory-evidence")
    for flag in ("--sha", "--full-nodes", "--gate-nodes", "--out"):
        p.add_argument(flag, required=True)
    p = sub.add_parser("aggregate")
    for flag in ("--evidence-dir", "--sha", "--needs-env"):
        p.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    if args.command == "aggregate":
        try:
            needs = json.loads(os.environ.get(args.needs_env, ""))
        except ValueError:
            needs = {}
        summary = aggregate(Path(args.evidence_dir), sha=args.sha, needs=needs)
        print_aggregate(summary)
        return 0 if summary["result"] == "PASS" else 1
    try:
        manifest = load_manifest()
        errors = validate_manifest(manifest)
        if errors:
            print("MANIFEST_INVALID " + " ".join(errors), file=sys.stderr)
            return 2
        if args.command == "validate":
            print(f"MANIFEST_VALID shards={len(manifest['shards'])} gate_files={len(gate_files(manifest))} "
                  f"offloaded_files={len(offloaded_files(manifest))}")
        elif args.command == "gate-addopts":
            print(gate_addopts(manifest))
        elif args.command == "shard-ids":
            print(json.dumps([shard["id"] for shard in manifest["shards"]]))
        elif args.command == "shard-argv":
            print(json.dumps(shard_argv(manifest, args.shard, data_file=args.data_file, nodes_file=args.nodes_file)))
        elif args.command == "collect-argv":
            print(json.dumps(collect_argv(manifest, args.partition, nodes_file=args.nodes_file)))
        elif args.command == "shard-evidence":
            write_shard_evidence(Path(args.out), shard_id=args.shard, sha=args.sha, exit_code=int(args.exit_code),
                                 seconds=float(args.seconds), nodes_file=Path(args.nodes_file),
                                 data_file=Path(args.data_file))
        elif args.command == "gate-evidence":
            write_gate_evidence(Path(args.out), sha=args.sha, exit_code=int(args.exit_code),
                                report=Path(args.report), data_file=Path(args.data_file))
        elif args.command == "inventory-evidence":
            write_inventory_evidence(Path(args.out), sha=args.sha, full_nodes=Path(args.full_nodes),
                                     gate_nodes=Path(args.gate_nodes))
    except (ShardError, OSError, ValueError, KeyError, TypeError, core_safety_plan.PlanExtractionError) as exc:
        print(f"SHARDING_INVALID: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
