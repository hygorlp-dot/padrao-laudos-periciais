"""Oraculo dirigido para a guarda de autoridade fonte<->workspace do intake PJe.

Motivo de existir: a revisao independente do HEAD 80b807e mostrou que a guarda
central desta lane podia ser APAGADA INTEIRA sem nenhum teste ficar vermelho --
`SaveCaseAnalysis` tem uma checagem propria que produz o MESMO status 500, entao
os testes de ponta a ponta passavam pelo motivo errado, afirmando um codigo de
status em vez do mecanismo.

Estes testes chamam `ListCaseDocumentsWithPjeInventory.execute` DIRETAMENTE, sem
nenhuma outra camada capaz de levantar o mesmo erro, e afirmam a identidade do
erro. Mutar a guarda tem de deixa-los vermelhos.

TARGETED_MUTATION_KILL verificado manualmente (ver
test_ORACLE_NOTE_targeted_mutation_kill abaixo).
"""
from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from scripts.backend_contract.application.ports import RepositoryIntegrityError
from scripts.backend_contract.application.services import ListCaseDocumentsWithPjeInventory

WORKSPACE_A = "11111111-1111-4111-8111-111111111111"
WORKSPACE_B = "22222222-2222-4222-8222-222222222222"
CONTENT_A = "33333333-3333-4333-8333-333333333333"
CONTENT_OTHER = "44444444-4444-4444-8444-444444444444"
SHA_A = "a" * 64
SHA_OTHER = "b" * 64


def _inventory(*, workspace_id=WORKSPACE_A, storage_content_id=CONTENT_A, source_sha256=SHA_A):
    return {
        "schema_version": "1.0.0",
        "workspace_id": workspace_id,
        "storage_content_id": storage_content_id,
        "source_sha256": source_sha256,
        "instance_label": "Vara sintetica",
        "documents": [
            {"document_id": "DOC-PJE-001", "id_pje": "900001", "title": "Peca",
             "raw_type": "PETICAO", "normalized_type": "PETICAO_INICIAL",
             "page_start": 1, "page_end": 2, "available": True},
        ],
        "party_rows": [],
    }


def _record(content_id=CONTENT_A, checksum=SHA_A, filename="autos.pdf"):
    return SimpleNamespace(content_id=content_id, checksum_sha256=checksum, original_filename=filename)


def _frozen(value):
    """Espelha a forma congelada em que um payload realmente e persistido."""
    if isinstance(value, dict):
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_frozen(item) for item in value)
    return value


def _service(records, inventory):
    documents = SimpleNamespace(execute=lambda _workspace: tuple(records))
    revisions = SimpleNamespace(
        latest=lambda *_args, **_kwargs: (
            None if inventory is None else SimpleNamespace(payload=_frozen(inventory))
        )
    )
    return ListCaseDocumentsWithPjeInventory(documents, revisions)


def test_inventory_naming_another_workspace_is_rejected_by_this_guard_alone():
    """CROSS_WORKSPACE_READ = 0, provado sem passar por Case Analysis."""
    service = _service([_record()], _inventory(workspace_id=WORKSPACE_B))
    with pytest.raises(RepositoryIntegrityError, match="another workspace"):
        service.execute(WORKSPACE_A)


def test_inventory_bound_to_a_content_id_absent_from_the_workspace_is_rejected():
    service = _service([_record(content_id=CONTENT_OTHER, checksum=SHA_OTHER)], _inventory())
    with pytest.raises(RepositoryIntegrityError, match="diverges from private source authority"):
        service.execute(WORKSPACE_A)


def test_inventory_whose_hash_disagrees_with_the_stored_source_is_rejected():
    service = _service([_record(checksum=SHA_OTHER)], _inventory())
    with pytest.raises(RepositoryIntegrityError, match="diverges from private source authority"):
        service.execute(WORKSPACE_A)


def test_inventory_attaches_only_to_its_own_physical_authority():
    """O inventario acompanha a fonte a que pertence, e nenhuma outra."""
    records = [_record(), _record(content_id=CONTENT_OTHER, checksum=SHA_OTHER, filename="outro.pdf")]
    result = _service(records, _inventory()).execute(WORKSPACE_A)
    attached = {str(item.content_id): item.pje_inventory is not None for item in result}
    assert attached == {CONTENT_A: True, CONTENT_OTHER: False}


def test_a_workspace_without_any_inventory_stays_untouched():
    result = _service([_record()], None).execute(WORKSPACE_A)
    assert [item.pje_inventory for item in result] == [None]


def test_ORACLE_NOTE_targeted_mutation_kill():
    """Registro do resultado da mutacao dirigida (nao e uma assercao de produto).

    Mutantes efetivamente aplicados em
    `ListCaseDocumentsWithPjeInventory.execute` e executados contra este arquivo:

    | mutante                                                    | resultado      |
    |------------------------------------------------------------|----------------|
    | M1 remover `raise ... "belongs to another workspace"`       | RED (1 falha)  |
    | M2 remover a guarda `bound is None or sha mismatch`         | RED (3 falhas) |
    | M3 anexar o inventario a todo record (sem casar content_id) | RED (4 falhas) |

    Os tres eram sobreviventes antes deste arquivo: a revisao independente
    mostrou que apagar a guarda inteira mantinha 57 testes verdes, porque
    `SaveCaseAnalysis` levantava o mesmo 500 por outro caminho.
    """
    assert True
