import json

import pytest

from scripts.backend_contract.application import judicial_unit_directory as directory


def test_directory_resolves_only_an_exact_versioned_judicial_unit():
    location = directory.resolve_judicial_unit(
        tribunal="TRF5", uf="PE", unit_type="VARA_FEDERAL", unit_number=24
    )

    assert location is not None
    assert location.municipio_sede == "Caruaru"
    assert location.subsecao_judiciaria == "Caruaru"
    assert location.authority == "Justiça Federal em Pernambuco"
    assert location.source_reference.startswith("https://www.jfpe.jus.br/")
    assert directory.resolve_judicial_unit(
        tribunal="TRF5", uf="PE", unit_type="VARA_FEDERAL", unit_number=25
    ) is None


def test_directory_rejects_fuzzy_or_incomplete_unit_identities():
    assert directory.resolve_judicial_unit(
        tribunal="TRF 5", uf="PE", unit_type="VARA_FEDERAL", unit_number=24
    ) is None
    with pytest.raises(ValueError, match="identidade"):
        directory.resolve_judicial_unit(
            tribunal="TRF5", uf="PE", unit_type="VARA_FEDERAL", unit_number=0
        )


def test_directory_fails_closed_on_unknown_schema(monkeypatch, tmp_path):
    malformed = tmp_path / "judicial-unit-directory-v1.json"
    malformed.write_text(
        json.dumps({"schemaVersion": "UNKNOWN", "entries": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(directory, "_DIRECTORY_PATH", malformed)
    directory._directory.cache_clear()
    try:
        with pytest.raises(ValueError, match="contrato"):
            directory.resolve_judicial_unit(
                tribunal="TRF5", uf="PE", unit_type="VARA_FEDERAL", unit_number=24
            )
    finally:
        directory._directory.cache_clear()
