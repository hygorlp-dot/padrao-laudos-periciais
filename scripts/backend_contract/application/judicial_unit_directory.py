"""Diretório local, versionado e fail-closed de unidades judiciais."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_DIRECTORY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "judicial-unit-directory-v1.json"
)
_ROOT_KEYS = {"schemaVersion", "entries"}
_ENTRY_KEYS = {
    "tribunal",
    "uf",
    "unitType",
    "unitNumber",
    "municipioSede",
    "subsecaoJudiciaria",
    "authority",
    "sourceReference",
    "effectiveInformation",
}


@dataclass(frozen=True, slots=True)
class JudicialUnitLocation:
    municipio_sede: str
    subsecao_judiciaria: str
    authority: str
    source_reference: str
    effective_information: str


def _required_text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} inválido no diretório judicial")
    return value


@lru_cache(maxsize=1)
def _directory() -> dict[tuple[str, str, str, int], JudicialUnitLocation]:
    try:
        payload = json.loads(_DIRECTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("diretório judicial indisponível ou malformado") from exc
    if (
        type(payload) is not dict
        or set(payload) != _ROOT_KEYS
        or payload["schemaVersion"] != "JUDICIAL_UNIT_DIRECTORY_V1"
        or type(payload["entries"]) is not list
    ):
        raise ValueError("contrato do diretório judicial inválido")
    result = {}
    for raw in payload["entries"]:
        if type(raw) is not dict or set(raw) != _ENTRY_KEYS:
            raise ValueError("entrada do diretório judicial inválida")
        number = raw["unitNumber"]
        if type(number) is not int or number < 1:
            raise ValueError("número de unidade judicial inválido")
        source_reference = _required_text(raw["sourceReference"], "sourceReference")
        if not source_reference.startswith("https://www.jfpe.jus.br/"):
            raise ValueError("fonte do diretório judicial não é institucional")
        key = (
            _required_text(raw["tribunal"], "tribunal").upper(),
            _required_text(raw["uf"], "uf").upper(),
            _required_text(raw["unitType"], "unitType").upper(),
            number,
        )
        if key in result:
            raise ValueError("unidade judicial duplicada")
        result[key] = JudicialUnitLocation(
            municipio_sede=_required_text(raw["municipioSede"], "municipioSede"),
            subsecao_judiciaria=_required_text(
                raw["subsecaoJudiciaria"], "subsecaoJudiciaria"
            ),
            authority=_required_text(raw["authority"], "authority"),
            source_reference=source_reference,
            effective_information=_required_text(
                raw["effectiveInformation"], "effectiveInformation"
            ),
        )
    return result


def resolve_judicial_unit(
    *, tribunal: str, uf: str, unit_type: str, unit_number: int
) -> JudicialUnitLocation | None:
    if (
        type(tribunal) is not str
        or type(uf) is not str
        or type(unit_type) is not str
        or type(unit_number) is not int
        or unit_number < 1
    ):
        raise ValueError("identidade de unidade judicial inválida")
    return _directory().get(
        (tribunal.upper(), uf.upper(), unit_type.upper(), unit_number)
    )
