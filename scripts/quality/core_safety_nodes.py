"""Plugin pytest de inventário exato de node IDs (V7-4A, #259).

Carregado somente por ``-p scripts.quality.core_safety_nodes`` nas invocações
que precisam provar o inventário (shards de regressão e coleta de referência).
Não altera coleta, seleção, ordem nem resultado: apenas observa e grava, em
``--core-safety-nodes=<arquivo>``, os node IDs coletados e o desfecho de cada
um. Nunca decide PASS/FAIL.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "CORE_SAFETY_NODE_REPORT_V1"
_STATE: dict = {}


def pytest_addoption(parser):
    parser.addoption("--core-safety-nodes", action="store", default=None,
                     help="grava o inventário exato de node IDs coletados/executados")


def pytest_configure(config):
    target = config.getoption("--core-safety-nodes")
    _STATE.clear()
    if target:
        _STATE.update(target=Path(target), collected=None, outcomes={})


def pytest_collection_finish(session):
    if _STATE:
        _STATE["collected"] = [item.nodeid for item in session.items]


def pytest_runtest_logreport(report):
    if not _STATE:
        return
    outcomes = _STATE["outcomes"]
    if report.failed:
        outcomes[report.nodeid] = "failed"
    elif report.skipped and report.nodeid not in outcomes:
        outcomes[report.nodeid] = "skipped"
    elif report.when == "call" and report.passed and outcomes.get(report.nodeid) != "failed":
        outcomes[report.nodeid] = "passed"


def pytest_sessionfinish(session, exitstatus):
    if not _STATE:
        return
    payload = {
        "schema": SCHEMA,
        "exitstatus": int(exitstatus),
        "collect_only": bool(session.config.getoption("collectonly")),
        "collected": sorted(_STATE["collected"] or []),
        "outcomes": dict(sorted(_STATE["outcomes"].items())),
    }
    _STATE["target"].write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
